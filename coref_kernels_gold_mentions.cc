#include <map>

#include "tensorflow/core/framework/op.h"
#include "tensorflow/core/framework/shape_inference.h"
#include "tensorflow/core/framework/op_kernel.h"

using namespace tensorflow;

REGISTER_OP("ExtractSpans")
.Input("candidate_starts: int32")
.Input("candidate_ends: int32")
.Input("gold_starts: int32")
.Input("gold_ends: int32")
.Attr("sort_spans: bool")
.Output("output_span_indices: int32");

class ExtractSpansOp : public OpKernel {
public:
  explicit ExtractSpansOp(OpKernelConstruction* context) : OpKernel(context) {
    OP_REQUIRES_OK(context, context->GetAttr("sort_spans", &_sort_spans));
  }

  void Compute(OpKernelContext* context) override {
    TTypes<int32>::ConstVec candidate_starts = context->input(0).vec<int32>();
    TTypes<int32>::ConstVec candidate_ends = context->input(1).vec<int32>();
    TTypes<int32>::ConstVec gold_starts = context->input(2).vec<int32>();
    TTypes<int32>::ConstVec gold_ends = context->input(3).vec<int32>();

    Tensor* output_span_indices_tensor = nullptr;
    TensorShape output_span_indices_shape({1, gold_starts.size()});
    OP_REQUIRES_OK(context, context->allocate_output(0, output_span_indices_shape,
                                                     &output_span_indices_tensor));
    TTypes<int32>::Matrix output_span_indices = output_span_indices_tensor->matrix<int32>();

    /* check whether duplicated elements in gold and candidates; results: NO DUPLICATED
    for (int i=0; i<gold_starts.size(); i++) {
       int counter = 0;
       for (int j=0; j<gold_starts.size(); j++) {
            if (gold_starts(i) == gold_starts(j) && gold_ends(i) == gold_ends(j)) {
               counter ++;
            }
       }
       if (counter != 1) {
          exit(1);
       }
    }

    for (int i=0; i<candidate_starts.size(); i++) {
       int counter = 0;
       for (int j=0; j<candidate_starts.size(); j++) {
            if (candidate_starts(i) == candidate_starts(j) && candidate_ends(i) == candidate_ends(j)) {
               counter ++;
            }
       }
       if (counter != 1) {
          exit(1);
       }
    }
    */




    /*** non sorted version
    int x = 0;
    for (int j=0; j<gold_starts.size(); j++) {
        for (int i=0; i<candidate_starts.size(); i++) {
            int32 start = candidate_starts(i);
            int32 end = candidate_ends(i);
            if (gold_starts(j) == start && gold_ends(j) == end) {
               output_span_indices(0, x) = i;
               x++;
               break;
            }
        }
    }
    ***/


    /*** sorted version */
    std::vector<int> top_span_indices;

    int x = 0;
    for (int j=0; j<gold_starts.size(); j++) {
        for (int i=0; i<candidate_starts.size(); i++) {
            int32 start = candidate_starts(i);
            int32 end = candidate_ends(i);
            if (gold_starts(j) == start && gold_ends(j) == end) {
               if (_sort_spans) {
                 top_span_indices.push_back(i);
               } else {
                 output_span_indices(0, x) = i;
               }
               x++;
               break;
            }
        }
    }

    // just a check
    if (x != gold_starts.size()) {
      exit(1);
    }

    if (_sort_spans) {
      std::sort(top_span_indices.begin(), top_span_indices.end(),
                [&candidate_starts, &candidate_ends] (int i1, int i2) {
                  if (candidate_starts(i1) < candidate_starts(i2)) {
                    return true;
                  } else if (candidate_starts(i1) > candidate_starts(i2)) {
                    return false;
                  } else if (candidate_ends(i1) < candidate_ends(i2)) {
                    return true;
                  } else if (candidate_ends(i1) > candidate_ends(i2)) {
                    return false;
                  } else {
                    return i1 < i2;
                  }
                });
      for (int i = 0; i < gold_starts.size(); ++i) {
        output_span_indices(0, i) = top_span_indices[i];
      }
    }
    /*****/


    // check whether some duplicated element in output_span_indices
    /*
    for (int i=0; i<gold_starts.size(); i++) {
       int counter = 0;
       for (int j=0; j<gold_starts.size(); j++) {
            if (output_span_indices(0, i) == output_span_indices(0, j) && output_span_indices(0, i) == output_span_indices(0, j)) {
               counter ++;
            }
       }
       if (counter != 1) {
          exit(1);
       }
    }
    */


  }
private:
  bool _sort_spans;
};

REGISTER_KERNEL_BUILDER(Name("ExtractSpans").Device(DEVICE_CPU), ExtractSpansOp);
